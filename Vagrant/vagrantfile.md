# Конфигурационный файл Vagrantfile

`Vagrantfile` — это сердце любого проекта Vagrant. Это Ruby-файл, который описывает, как сконфигурировать и настроить виртуальные машины.

## Структура и синтаксис

Файл использует простой DSL (предметно-ориентированный язык) на основе Ruby, но знание Ruby не является обязательным для базовой конфигурации.

```ruby
# Указываем версию синтаксиса Vagrantfile. "2" - актуальная версия.
Vagrant.configure("2") do |config|
  # config - это объект, через который настраивается ВМ.
  # Все параметры задаются здесь.
end
```

## Ключевые параметры конфигурации

Ниже представлены наиболее часто используемые параметры.

| Параметр | Пример | Описание |
| --- | --- | --- |
| `config.vm.box` | `"ubuntu/jammy64"` | Определяет базовый образ (box) для установки. Vagrant автоматически скачает его, если образа нет в кэше. |
| `config.vm.box_version` | `"20240912.0.0"` | Указывает конкретную версию образа для использования. |
| `config.vm.box_check_update` | `false` | Отключает автоматическую проверку обновлений для box'а при каждом `vagrant up`. |
| `config.vm.hostname` | `"web-server"` | Устанавливает имя хоста (hostname) внутри гостевой ВМ. |
| `config.ssh.username` | `"admin"` | Имя пользователя для SSH-подключения. По умолчанию `vagrant`. |
| `config.ssh.private_key_path` | `"~/.ssh/id_rsa"` | Путь к приватному SSH-ключу для подключения к ВМ. |
| `config.vm.boot_timeout` | `600` | Время ожидания (в секундах), которое Vagrant будет ждать загрузки ВМ. |

### Пример простого Vagrantfile

```ruby
Vagrant.configure("2") do |config|
  # 1. Определение базового образа
  config.vm.box = "ubuntu/jammy64"
  config.vm.box_version = "20240912.0.0"

  # 2. Настройка имени хоста
  config.vm.hostname = "my-dev-machine"

  # 3. Настройка сети (проброс порта 8080 хоста на 80 гостя)
  config.vm.network "forwarded_port", guest: 80, host: 8080

  # 4. Настройка провайдера (увеличение памяти для VirtualBox)
  config.vm.provider "virtualbox" do |v|
    v.memory = 2048
  end

  # 5. Автоматическая установка ПО (provisioning)
  config.vm.provision "shell", inline: "apt-get update && apt-get install -y nginx"
end
```

Детальную информацию по конкретным блокам конфигурации можно найти в соответствующих разделах:
- **Сеть:** `vagrant_networking.md`
- **Provisioning:** `vagrant_provisioning.md`
- **Провайдеры:** `vagrant_providers.md`
- **Хранилище:** `vagrant_storage_and_folders.md`
