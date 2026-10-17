# Провайдеры и образы (Boxes) в Vagrant

**Актуально для:** Vagrant 2.4.x

## Определения

**Провайдер (Provider)** — программный слой или «движок» виртуализации, который Vagrant использует для создания и управления виртуальными машинами. Vagrant служит унифицированным интерфейсом, абстрагирующим работу с различными гипервизорами (VirtualBox, Libvirt, VMware, Hyper-V), контейнеризаторами (Docker) и локальными эмуляторами (QEMU). Облачные платформы (AWS, Azure, GCP) рассматриваются отдельно и не являются предметом этого раздела.

**Образ (Box)** — базовый шаблон виртуальной машины, упакованный в специфический формат Vagrant. Содержит предустановленную операционную систему, настроенного пользователя (обычно `vagrant`) и минимальный набор системных инструментов. Образы **жестко привязаны к провайдеру**: один и тот же `.box` файл не может использоваться с VirtualBox и Libvirt одновременно, так как включает диск в формате конкретного гипервизора и провайдер-специфичный `metadata.json`.

**Структура `.box` файла:**
Фактически это тарбол (обычно `.tar.gz`), содержащий:
- `metadata.json` — описывает поддерживаемого провайдера, версию образа и необходимые параметры.
- `Vagrantfile` — специфические настройки по умолчанию для этого образа (например, имя пользователя, коммуникатор).
- `box.ovf` / `*.qcow2` / `*.vmdk` — образ диска в формате, соответствующем провайдеру.

## Форматы и привязка образов к провайдерам

Vagrant хранит образы в кэше `~/.vagrant.d/boxes/`. При добавлении образа Vagrant определяет его провайдер из `metadata.json`. При конфликте провайдеров Vagrant выдаст ошибку на этапе `vagrant up`, так как диск одного формата не может быть смонтирован другим гипервизором.

### Провайдер-специфичные форматы дисков

| Провайдер | Формат диска | Где используется |
| :--- | :--- | :--- |
| **VirtualBox** | `vmdk`, `ovf` | Кроссплатформенный стандарт |
| **Libvirt/KVM** | `qcow2` | Linux сервера, максимальная производительность |
| **VMware** | `vmdk` | Корпоративные среды, требуется плагин `vagrant-vmware-desktop` |
| **Hyper-V** | `vhd` / `vhdx` | Windows Server |
| **QEMU (Apple Silicon)** | `qcow2`, `img` | macOS ARM64 через `vagrant-qemu` |
| **Docker** | Нет диска | Образы Docker Hub, контейнеры |

### Мульти-провайдерные метаданные (box metadata)

Один и тот же базовый образ может поставляться в виде нескольких `.box` файлов под разные провайдеры. Vagrant Cloud хранит такие метаданные и автоматически выбирает нужный артефакт. Пример `metadata.json` для образа с поддержкой двух провайдеров:

```json
{
  "name": "my-org/ubuntu-24.04",
  "description": "Ubuntu 24.04 for VirtualBox and Libvirt",
  "versions": [
    {
       "version": "202510.26.0",
      "providers": [
        {
          "name": "virtualbox",
          "url": "https://example.com/ubuntu-24.04-virtualbox-202510.26.0.box",
          "checksum_type": "sha256",
          "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        },
        {
          "name": "libvirt",
          "url": "https://example.com/ubuntu-24.04-libvirt-202510.26.0.box",
          "checksum_type": "sha256",
          "checksum": "a3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b856"
        }
      ]
    }
  ]
}
```

### `box_url` и резервные источники

Вместо имени `box` можно указать прямую ссылку на `.box` файл. Это полезно для внутренних зеркал или образов не из Vagrant Cloud:

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.box_url = "https://artifacts.example.com/vagrant/ubuntu-24.04.box"
  config.vm.box_download_checksum = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  config.vm.box_download_checksum_type = "sha256"
end
```

## Базовые концепции

### Взаимосвязь провайдеров и образов

Образы жестко привязаны к провайдеру из-за различий в форматах дисков и метаданных. При попытке запустить ВМ с несовместимым провайдером Vagrant выдаст ошибку.

**Просмотр установленных образов:**
```bash
# Список локальных образов с указанием их провайдеров и версий
vagrant box list
```

### Механизм выбора провайдера (Provider Selection)

Если в `Vagrantfile` описано несколько провайдеров, Vagrant выбирает один по следующим правилам (в порядке приоритета):
1.  Явное указание в CLI: `vagrant up --provider=libvirt`.
2.  Переменная окружения: `export VAGRANT_DEFAULT_PROVIDER=virtualbox`.
3.  Первый найденный блок `config.vm.provider` в `Vagrantfile`.
4.  Наличие установленного гипервизора в системе (по умолчанию ищется VirtualBox).

### Версионирование образов

Vagrant поддерживает версионирование образов, что позволяет фиксировать окружение для всей команды.

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
   # Оператор ~> означает "совместимую с 202510.26" (например, 202510.26.0)
   config.vm.box_version = "~> 202510.26.0"
end
```

### Поддерживаемые провайдеры и плагины

| Провайдер | Плагин | Статус |
| :--- | :--- | :--- |
| **virtualbox** | Встроен | Стандартный, кроссплатформенный |
| **libvirt** | `vagrant-libvirt` | Рекомендуется для Linux, производительность KVM |
| **vmware_desktop** | `vagrant-vmware-desktop` | Платный, стабильная работа с VMware Workstation/Fusion |
| **hyperv** | Встроен | Только Windows |
| **qemu** | `vagrant-qemu` | macOS (Apple Silicon/Intel), Linux, Windows; эмуляция ARM64/x86_64 |
| **docker** | Встроен | Контейнеры как ВМ |
| **parallels** | `vagrant-parallels` | macOS x86_64/ARM64, Parallels Desktop |
| **podman** | `vagrant-podman` | Linux/macOS, альтернатива Docker-провайдеру на базе Podman |

### Предварительные требования

Выбор провайдера определяется хост-платформой и требованиями к производительности. Перед началом работы:

| Платформа | Рекомендуемый провайдер | Установка |
| :--- | :--- | :--- |
| **Linux** | Libvirt (KVM) | `sudo apt install libvirt-daemon-system qemu-kvm` + `vagrant plugin install vagrant-libvirt` |
| **macOS (Intel)** | VirtualBox или VMware | VirtualBox [скачать](https://www.virtualbox.org/wiki/Downloads) или VMware Fusion + `vagrant plugin install vagrant-vmware-desktop` |
| **macOS (Apple Silicon)** | QEMU или Parallels | `vagrant plugin install vagrant-qemu` или `vagrant plugin install vagrant-parallels` |
| **Windows** | Hyper-V или VirtualBox | Включить Hyper-V через `Enable-WindowsOptionalFeature` или установить VirtualBox |

**Проверка готовности:**
```bash
# Linux: убедиться, что KVM загружен
lsmod | grep kvm
# → kvm_intel или kvm_amd в выводе

# macOS: проверить VT-x
sysctl -n machdep.cpu.features | grep VMX
# → VMX в выводе означает поддержку аппаратной виртуализации

# Windows: проверить Hyper-V
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V
```

## Практические сценарии

### Сценарий 1: Конфигурация гипервизоров

**Настройка Libvirt (рекомендуется для Linux):**
Требует плагин `vagrant-libvirt`. Обеспечивает почти нативную производительность KVM.

```ruby
config.vm.provider "libvirt" do |lv|
  lv.memory = 4096
  lv.cpus = 4
  lv.nested = true                 # Включение вложенной виртуализации
  lv.cpu_mode = "host-passthrough" # Максимальная производительность CPU
  lv.storage_pool_name = "default" # Имя пула в libvirt
  lv.management_network_name = "vagrant-libvirt"
  lv.machine_virtual_size = 50     # Размер диска (ГБ)
end
```

**Настройка VirtualBox (кроссплатформенный стандарт):**

```ruby
config.vm.provider "virtualbox" do |vb|
  vb.name = "dev-vm"
  vb.memory = 2048
  vb.cpus = 2
  vb.gui = false                   # Без графического окна
  vb.linked_clone = true           # Экономия места (copy-on-write клон)
  
  # Тюнинг параметров через VBoxManage
  vb.customize ["modifyvm", :id, "--natdnshostresolver1", "on"]
  vb.customize ["modifyvm", :id, "--vram", "128"]
end
```

**Настройка VMware Workstation/Fusion (проверенная стабильность):**
Требует плагин `vagrant-vmware-desktop` (лицензия). Обеспечивает высокую производительность и лучшую совместимость с гостевыми ОС.

```ruby
config.vm.provider "vmware_desktop" do |vmware|
  vmware.vmx["memsize"] = "4096"
  vmware.vmx["numvcpus"] = "4"
  vmware.vmx["cpuid.coresPerSocket"] = "2"
  vmware.linked_clone = true
end
```

**Настройка Hyper-V (Windows):**

```ruby
config.vm.provider "hyperv" do |h|
  h.cpus = 2
  h.memory = 2048
  h.maxmemory = 4096
  h.vmname = "hyperv-dev-node"
end
```

**Настройка QEMU (Apple Silicon и другие платформы):**
Требует плагин `vagrant-qemu`. На macOS использует Apple Hypervisor.framework; на Linux — KVM; на Windows — WHPX.

```ruby
config.vm.provider "qemu" do |qemu|
  qemu.machine = "virt,accel=hvf"
  qemu.smp = "cpus=4"    # Количество vCPUs (ppggff/vagrant-qemu 0.6.0)
  qemu.memory = "4G"
  qemu.arch = "aarch64"
end
```

### Сценарий 2: Использование Docker как провайдера

Позволяет запускать контейнеры как если бы это были полноценные ВМ (без накладных расходов на гипервизор).

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "docker" do |d|
    d.image = "ubuntu:24.04"
    d.privileged = true
    d.has_ssh = true               # Требует наличия SSH-сервера в контейнере
    d.remains_running = true       # Не останавливать контейнер после up
  end
end
```

### Сценарий 3: Мульти-провайдерный Vagrantfile

При работе в гетерогенной среде (разные ОС у разработчиков) удобно описывать несколько провайдеров в одном файле. Vagrant выберет тот, который доступен на текущей машине:

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # Linux: Libvirt (KVM)
  if Vagrant::Util::Platform.linux?
    config.vm.provider "libvirt" do |lv|
      lv.memory = 2048
      lv.cpus = 2
      lv.nested = true
      lv.cpu_mode = "host-passthrough"
    end
  end

  # macOS: VirtualBox или QEMU
  if Vagrant::Util::Platform.darwin?
    config.vm.provider "virtualbox" do |vb|
      vb.memory = 2048
      vb.cpus = 2
      vb.linked_clone = true
    end
  end

  # Windows: Hyper-V или VirtualBox
  if Vagrant::Util::Platform.windows?
    config.vm.provider "hyperv" do |h|
      h.memory = 2048
      h.cpus = 2
    end
  end
end
```

### Сценарий 4: Создание собственного образа (Packaging)

Создание `.box` файла из текущей ВМ для передачи коллегам или reproducibility:

```bash
# 1. Подготовить ВМ: установить SSH-сервер, пользователя vagrant, ключи
# 2. Упаковать текущее состояние ВМ (не-running)
vagrant package --output custom-dev-box-2026.01.box

# 3. Проверить содержимое архива
tar -tzf custom-dev-box-2026.01.box | head -20
# → metadata.json
# → Vagrantfile
# → box.ovf
# → ...
```

Для повторяемых сборок используйте [Packer](https://www.packer.io/) — он позволяет описать образ как код (HCL/JSON) и автоматически собирать `.box` для нескольких провайдеров.

### Сценарий 5: Жизненный цикл образов

**Обновление и очистка:**
```bash
# Проверить наличие новых версий для всех образов проекта
vagrant box outdated

# Обновить конкретный образ
vagrant box update --box bento/ubuntu-24.04

# Удалить все неиспользуемые (старые) версии образов
vagrant box prune
```

**Добавление из внешних источников:**
```bash
# Из Vagrant Cloud
vagrant box add bento/ubuntu-24.04

# Из локального файла или URL
vagrant box add my-custom-box ./package.box

# С указанием провайдера (если box поддерживает несколько)
vagrant box add my-custom-box ./package.box --provider libvirt
```

### Сценарий 6: Проверка целостности образа

```bash
# Список образов с указанием провайдера и версии ( Vagrant Cloud поддерживает
# контрольные суммы, но команда `vagrant box list` их не выводит напрямую)
vagrant box list
# → bento/ubuntu-24.04 (202510.26.0, virtualbox)

# Проверка контрольной суммы при добавлении нового образа
vagrant box add bento/ubuntu-24.04 --provider virtualbox \
  --checksum sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 \
  --checksum-type sha256
# → Confirming box checksum...

# Принудительная перепроверка и повторная загрузка
vagrant box update --box bento/ubuntu-24.04 --insecure
```

### Сценарий 7: Выбор провайдера в CI/CD

В пайплайнах используйте переменные окружения для явного указания провайдера:

```bash
# .gitlab-ci.yml или .github/workflows
export VAGRANT_DEFAULT_PROVIDER=libvirt
export VAGRANT_NO_TTY=1
export VAGRANT_LOG=info

vagrant up --no-provision
vagrant provision
vagrant ssh -c "run-tests.sh"
vagrant destroy -f
```

Для Docker-провайдера в CI/CD:

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "docker" do |d|
    d.image = "docker:24.0-dind"
    d.has_ssh = false
    d.remains_running = false
  end
end
```

### Сценарий 8: UEFI, Secure Boot и TPM (Libvirt)

Современные гостевые ОС и проверки безопасности требуют UEFI-прошивку (OVMF) и, для расширенных сценариев, TPM-устройство. Требуется машина типа `q35`.

```ruby
config.vm.provider "libvirt" do |lv|
  lv.machine_type = "pc-q35-6.2"           # UEFI поддерживается только на q35
  lv.loader = "/usr/share/OVMF/OVMF_CODE.fd"   # UEFI-прошивка (на Debian/Ubuntu: /usr/share/OVMF/)
  lv.nvram  = "/path/to/OVMF_VARS.fd"          # переменные UEFI (копия, не системный файл!)

  # TPM: только если указан путь или версия — иначе опции игнорируются
  lv.tpm_model = "tpm-tis"
  lv.tpm_type = "passthrough"                  # или "emulator" (требует пакеты swtpm/swtpm-tools)
  lv.tpm_path = "/dev/tpm0"                    # аппаратный TPM хоста
  # для программного TPM: lv.tpm_version = "2.0" без tpm_path
end
```

**Secure Boot:** активируется UEFI-прошивкой с подписанными переменными (`OVMF_CODE.secboot.fd`) и загрузкой подписанных шлагрузов (shim). Из-за необходимости загрузки подписанного ядра Secure Boot в Vagrant настраивается на уровне box/прошивки, а не «одной строкой»: подготовьте гостя как образ с UEFI+Secure Boot (см. [Packer и Пайплайн box](./vagrant_packer_boxes.md)).

### Сценарий 9: PCI/GPU passthrough (Libvirt)

Проброс физических устройств в гостя требует: IOMMU на хосте (`intel_iommu=on`/`amd_iommu=on` ядре), привязки устройства к `vfio-pci` и указания адреса PCI в конфигурации.

```ruby
config.vm.provider "libvirt" do |lv|
  lv.machine_type = "pc-q35-6.2"
  lv.memory = 8192
  lv.cpus = 4

   # Адрес устройства из `lspci -nn` (например, GPU: 01:00.0)
   lv.pci :domain => "0x0000", :bus => "0x01", :slot => "0x00", :function => "0x0"
   # Звук/второй узел GPU: lv.pci :domain => "0x0000", :bus => "0x01", slot => "0x00", function => "0x1"
end
```

Как получить адрес:

```bash
lspci -nn | grep -i vga
# → 01:00.0 VGA compatible controller ... [10de:1f06]
lspci -s 01:00.0 -nn   # полный адрес bus:slot.func
```

Также доступен проброс USB-устройств (`lv.usb`) и генератора энтропии (`lv.random`). Проброс GPU (GPU passthrough) далее требует драйверов гостевой ОС; в `lv.qemu_args` можно добавить низкоуровневые параметры QEMU при нестандартных конфигурациях.

## Дополнительная информация

### Сравнение провайдеров

| Провайдер | Тип | Производительность | Требует плагин | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Libvirt (KVM)** | Нативный | Максимальная | `vagrant-libvirt` | Linux сервера и рабочие станции. |
| **VirtualBox** | Hosted | Средняя | Встроен | Универсальное решение для обучения и macOS (x86_64). |
| **VMware Workstation/Fusion** | Hosted | Высокая | `vagrant-vmware-desktop` | Стабильность, работа с 3D, корпоративные среды. |
| **Hyper-V** | Нативный | Высокая | Встроен | Корпоративные Windows-системы. |
| **QEMU (HVF)** | Эмулятор/Гипервизор | Высокая (HVF/KVM) | `vagrant-qemu` | macOS (Apple Silicon, Intel), Linux, Windows. |
| **Docker** | Контейнер | Экстремальная | Встроен | Легковесные сервисы, CI/CD, тестовые среды. |

### Источники образов

Официальные образы Ubuntu в Vagrant Cloud больше не публикуются компанией Canonical (с 24.04 из-за перехода на BSL). Для Ubuntu используйте альтернативные источники или ссылки напрямую на облачные образы Canonical ([cloud-images.ubuntu.com](https://cloud-images.ubuntu.com/vagrant/)).

**Рекомендованные источники:**
- **Bento (Chef):** Проект по сборке чистых, минимизированных образов для большинства ОС (`bento/ubuntu-*`, `bento/debian-*`). Поддерживаются VirtualBox, Libvirt, VMware. Текущая версия `bento/ubuntu-24.04`: `202510.26.0`.
- **Generic (Lavabit):** Широкий выбор дистрибутивов с хорошей поддержкой разных провайдеров.
- **Debian / AlmaLinux:** Продолжают выпускать официальные качественные образы.
- **Собственные зеркала:** Для изолированных сред используйте `box_url` с внутренним HTTPS-сервером.

> **Примечание:** HCP Vagrant (HashiCorp Cloud Platform Vagrant registry) устаревает. Новые box больше не могут быть созданы после 1 октября 2026 года; существующие работают до 31 декабря 2026 года.

### Создание переносимых образов (Packaging)

Создание `.box` файла из текущей ВМ для передачи коллегам:
```bash
vagrant package --output stable-dev-env.box
```

Для автоматизированной сборки используйте Packer: он позволяет описать образ как код и собирать `.box` для нескольких провайдеров, включая пост-обработку и публикацию в Vagrant Cloud. Полный пайплайн — в [Packer и Пайплайн box](./vagrant_packer_boxes.md), а общая автоматизация образов ВМ — в [Image Automation](../Linux/Virtualization/vm_images/image_automation.md).

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `The box 'bento/ubuntu-24.04' could not be found` | Неверное имя box или отсутствует провайдер | `vagrant box add bento/ubuntu-24.04 --provider virtualbox` |
| `No matching downloader for provider` | Не установлен плагин провайдера | `vagrant plugin install vagrant-libvirt` или `vagrant plugin install vagrant-vmware-desktop` |
| `Box format mismatch` | Попытка запуска qcow2-образа в VirtualBox | Используйте `vagrant up --provider=libvirt` или скачайте box для нужного провайдера |
| `VT-x is not available` | Hyper-V захватил аппаратную виртуализацию | Отключите Hyper-V или используйте `vagrant up --provider=hyperv` |
| `Plugin error` | Несовместимость версий плагинов | `vagrant plugin update` или переустановите плагин |

### См. также

- [Установка Vagrant](./vagrant_installation.md) — установка провайдеров и плагинов.
- [Vagrantfile: Справочник](./vagrantfile.md) — базовые параметры и синтаксис.
- [Vagrant на Apple Silicon](./vagrant_macos_apple_silicon.md) — особенности QEMU/ARM64.
- [Packer и Пайплайн box](./vagrant_packer_boxes.md) — сборка `.box` через Packer и публикация в Vagrant Cloud.
- [Плагины и команды](./vagrant_plugins_and_commands.md) — экосистема плагинов, `cloud`, `upload`, `validate`.
- [Vagrant и альтернативы](./vagrant_vs_alternatives.md) — сравнение с Docker, Terraform, Minikube.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md) — решение проблем с провайдерами.
