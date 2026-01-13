# Провайдеры и образы (Boxes) в Vagrant

Vagrant является оболочкой для систем виртуализации, которые называются **провайдерами**. Самые популярные провайдеры — VirtualBox, Libvirt (KVM/QEMU), Hyper-V и VMware.

**Образ (Box)** — это базовый шаблон виртуальной машины, который Vagrant использует для клонирования новых систем.

## Поиск образов (Boxes)

Найти нужный образ Vagrant можно на официальном портале: **[HashiCorp Vagrant Cloud](https://portal.cloud.hashicorp.com/vagrant/discover)**.

Портал позволяет фильтровать образы по имени, популярности и поддержке определенного провайдера (`libvirt`, `virtualbox` и т.д.).

## Настройка провайдера

Вы можете указать, какой провайдер использовать, и настроить его параметры для конкретной ВМ прямо в `Vagrantfile`.

**Пример настройки libvirt-провайдера:**
```ruby
Vagrant.configure("2") do |config|
  # ... другие настройки ...

  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 2048
    libvirt.cpus = 2
    # Использование virtio для лучшей производительности дисков и сети
    libvirt.disk_bus = 'virtio'
    libvirt.nic_model_type = 'virtio'
    libvirt.arch = 'x86_64'
    libvirt.os_type = 'linux'
    libvirt.graphics_type = 'vnc'
    libvirt.nested = true # Разрешить вложенную виртуализацию (KVM внутри KVM)
  end
end
```

## Смена провайдера

Чтобы сменить провайдера для существующего проекта (например, с VirtualBox на libvirt), необходимо **удалить директорию `.vagrant`** в каталоге с `Vagrantfile`. Эта директория хранит метаданные о созданных машинах, включая информацию о текущем провайдере.

```bash
# Удалить метаданные текущего провайдера
rm -rf .vagrant

# Запустить окружение с новым провайдером
vagrant up --provider=libvirt
```
После этого команда `vagrant up` будет использовать нового провайдера, указанного в `Vagrantfile` или в командной строке.
