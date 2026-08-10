# Провайдеры и образы (Boxes) в Vagrant

## Определения

**Провайдер (Provider)** — программный слой или «движок» виртуализации, который Vagrant использует для создания и управления виртуальными машинами. Vagrant служит унифицированным интерфейсом, абстрагирующим работу с различными гипервизорами (VirtualBox, Libvirt, VMware), контейнеризаторами (Docker) и облачными платформами (AWS, Azure).

**Образ (Box)** — базовый шаблон виртуальной машины, упакованный в специфический формат Vagrant. Содержит предустановленную операционную систему, настроенного пользователя (обычно `vagrant`) и минимальный набор системных инструментов.

**Структура `.box` файла:**
Фактически это тарбол (обычно `.tar.gz`), содержащий:
- `metadata.json` — описывает поддерживаемого провайдера.
- `Vagrantfile` — специфические настройки по умолчанию для этого образа (например, имя пользователя).
- `box.ovf` / `*.qcow2` / `*.vmdk` — образ диска в формате, соответствующем провайдеру.

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
  # Оператор ~> означает "совместимая с 202501" (например, 202501.1)
  config.vm.box_version = "~> 202501.0"
end
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

**Настройка Hyper-V (Windows):**

```ruby
config.vm.provider "hyperv" do |h|
  h.cpus = 2
  h.memory = 2048
  h.maxmemory = 4096
  h.vmname = "hyperv-dev-node"
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

### Сценарий 3: Управление жизненным циклом образов

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
```

## Дополнительная информация

### Сравнение провайдеров

| Провайдер | Тип | Производительность | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Libvirt (KVM)** | Нативный | Максимальная | Linux сервера и рабочие станции. |
| **VirtualBox** | Hosted | Средняя | Универсальное решение для обучения. |
| **Hyper-V** | Нативный | Высокая | Корпоративные Windows-системы. |
| **VMware** | Hosted | Высокая | Стабильность, работа с 3D (платный). |
| **Docker** | Контейнер | Экстремальная | Легковесные сервисы, CI/CD. |
| **QEMU** | Эмуляция | Высокая (HVF) | macOS (Apple Silicon). |

### Источники образов и Canonical (2026)

С 2026 года компания Canonical прекратила поддержку официальных образов Ubuntu в Vagrant Cloud (начиная с 24.04).
**Рекомендованные источники:**
- **Bento (Chef):** Проект по сборке чистых, минимизированных образов для большинства ОС (`bento/ubuntu-*`).
- **Generic (Lavabit):** Широкий выбор дистрибутивов с хорошей поддержкой разных провайдеров.
- **Debian / AlmaLinux:** Продолжают выпускать официальные качественные образы.

### Создание переносимых образов (Packaging)

Создание `.box` файла из текущей ВМ для передачи коллегам:
```bash
vagrant package --output stable-dev-env.box
```

### См. также

- [Установка Vagrant](./vagrant_installation.md) — установка провайдеров и плагинов.
- [Vagrantfile: Справочник](./vagrantfile.md) — базовые параметры и синтаксис.
- [Vagrant на Apple Silicon](./vagrant_macos_apple_silicon.md) — особенности QEMU/ARM64.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md) — решение проблем с провайдерами.
