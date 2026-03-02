# Провайдеры и образы (Boxes) в Vagrant

## Определения

1. **Провайдер (Provider)**
    * "Движок" виртуализации, используемый Vagrant для создания и управления ВМ. Vagrant выступает как унифицированная оболочка.
    * *Примеры*: VirtualBox, Libvirt (KVM/QEMU), Hyper-V, VMware, Docker.

2. **Образ (Box)**
    * Базовый шаблон ВМ, упакованный в формат Vagrant. Содержит минимальную ОС и служит основой для клонирования окружений.
    * **Важно:** Образы создаются для конкретных провайдеров — образ для VirtualBox несовместим с Libvirt.

> **Актуальность:** По состоянию на 2026 год Canonical прекратила выпуск официальных Vagrant-образов Ubuntu начиная с 24.04 (Noble Numbat). Используйте альтернативы от HashiCorp или Bento.

## Базовые концепции

### Взаимосвязь провайдеров и образов

**Критично:** Образы привязаны к провайдерам. При поиске box всегда проверяйте совместимость:

```bash
# Проверка доступных версий box для конкретного провайдера
vagrant box list | grep ubuntu

# Поиск образов на Vagrant Cloud
# https://portal.cloud.hashicorp.com/vagrant/discover
```

### Поиск образов

Официальный каталог — **[HashiCorp Vagrant Cloud](https://portal.cloud.hashicorp.com/vagrant/discover)**. Фильтрация по имени, провайдеру и версии.

**Популярные источники образов:**

| Источник | Описание | URL |
| --- | --- | --- |
| **HashiCorp** | Официальные образы от создателей Vagrant | `hashicorp/*` |
| **Bento (Chef)** | Образы для различных ОС и провайдеров | `bento/*` |
| **Ubuntu (старые)** | Официальные образы Canonical до 24.04 | `ubuntu/*` |
| **AlmaLinux** | Официальные образы AlmaLinux | `almalinux/*` |

## Практические сценарии

### Сценарий 1: Настройка параметров провайдера

**Пример для `libvirt`:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 2048
    libvirt.cpus = 2
    libvirt.disk_bus = 'virtio'      # Лучшая производительность дисков
    libvirt.nic_model_type = 'virtio' # Лучшая производительность сети
    libvirt.nested = true            # Вложенная виртуализация (KVM внутри KVM)
    libvirt.random_hostname = false  # Фиксированное hostname
  end
end
```

**Пример для `virtualbox`:**

```ruby
config.vm.provider "virtualbox" do |v|
  v.memory = 2048
  v.cpus = 2
  v.name = "my-vagrant-vm"          # Кастомное имя в VirtualBox
  v.gui = false                      # Запуск без GUI
  v.linked_clone = true              # Экономия места (клонирование от snapshot)
end
```

### Сценарий 2: Смена провайдера для проекта

**Процесс:**

1. **Уничтожьте существующую ВМ:**
    ```bash
    vagrant destroy -f
    ```

2. **Удалите метаданные провайдера:**
    ```bash
    rm -rf .vagrant
    ```

3. **Запустите с новым провайдером:**
    ```bash
    vagrant up --provider=libvirt
    ```

### Сценарий 3: Управление box'ами

**Работа с образами:**

```bash
# Добавить новый box
vagrant box add ubuntu/jammy64

# Добавить box с указанием версии
vagrant box add ubuntu/jammy64 --version 20240912.0.0

# Проверить наличие обновлений
vagrant box outdated

# Обновить box
vagrant box update

# Удалить box
vagrant box remove ubuntu/jammy64

# Проверить, где используется box
vagrant box list --name ubuntu/jammy64
```

### Сценарий 4: Выбор образа для Ubuntu 24.04

Поскольку Canonical прекратила выпуск официальных образов:

```ruby
# Вариант 1: Bento (рекомендуется)
config.vm.box = "bento/ubuntu-24.04"

# Вариант 2: HashiCorp (базовый)
config.vm.box = "hashicorp/bionic64"  # Старее, но стабильно

# Вариант 3: Сообщество
config.vm.box = "phz/noble64"

# Вариант 4: Использовать Ubuntu 22.04 LTS (продолжает обновляться)
config.vm.box = "ubuntu/jammy64"
```

## Дополнительная информация

### Сравнение провайдеров

| Провайдер | Платформа | Производительность | Примечание |
| --- | --- | --- | --- |
| **VirtualBox** | Кроссплатформенный | Средняя | Провайдер по умолчанию, прост в настройке |
| **Libvirt (KVM)** | Linux | Высокая | Нативная виртуализация Linux, требует плагин |
| **Hyper-V** | Windows | Высокая | Встроен в Windows Pro/Enterprise |
| **VMware** | Кроссплатформенный | Высокая | Проприетарный, требуется лицензия |
| **Docker** | Кроссплатформенный | Очень высокая | Контейнеры вместо полноценных ВМ |

### Рекомендации по выбору box

- **Разработка на Linux:** `bento/ubuntu-24.04` или `bento/debian-12` с провайдером Libvirt
- **Кроссплатформенная разработка:** `ubuntu/jammy64` с VirtualBox
- **Тестирование enterprise:** `almalinux/9` или `rockylinux/9`
- **Минимальный размер:** `generic/alpine318` или `generic/ubuntu2204`

### См. также

- [Vagrant Installation](./vagrant_installation.md) — установка Vagrant и плагинов
- [Vagrantfile Reference](./vagrantfile.md) — синтаксис конфигурации
- [Vagrant Networking](./vagrant_networking.md) — настройка сети
