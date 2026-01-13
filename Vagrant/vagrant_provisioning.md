# Provisioning (Автоматическая настройка) в Vagrant

Provisioning — это механизм, который позволяет автоматически устанавливать программное обеспечение, изменять конфигурации и выполнять другие подготовительные задачи при создании виртуальной машины. Это ключевая особенность для создания воспроизводимых окружений.

Provisioning-скрипты выполняются:
- При первом запуске `vagrant up`.
- При выполнении команды `vagrant provision`.
- Принудительно при `vagrant reload --provision`.

Vagrant поддерживает множество "провижинеров", включая Shell, Ansible, Puppet и Docker.

## Shell Provisioning

Это самый простой способ. Вы можете указать либо встроенный (inline) скрипт, либо путь к внешнему файлу `.sh`.

### Встроенный скрипт
Подходит для простых, коротких команд.

```ruby
config.vm.provision "shell", inline: "apt-get update && apt-get install -y nginx"
```

### Внешний скрипт
Рекомендуется для более сложных сценариев.

1.  **Создайте скрипт `provision.sh`:**
    ```bash
    #!/bin/bash
    set -euo pipefail # Останавливать скрипт при ошибках

    # Обновление пакетов
    apt-get update -y

    # Установка Nginx
    apt-get install -y nginx

    # Запуск и добавление в автозагрузку
    systemctl enable nginx
    systemctl start nginx
    ```

2.  **Подключите скрипт в `Vagrantfile`:**
    ```ruby
    config.vm.provision :shell, path: "provision.sh"
    ```

## Ansible Provisioning

Vagrant имеет встроенную поддержку Ansible, что делает его мощным инструментом для управления конфигурацией.

### Пример с Ansible
```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "playbook.yml"
  ansible.inventory_path = "inventory.ini"
end
```

### Как работает Ansible Provisioning?

Когда вы используете `ansible` в качестве провижинера, Vagrant автоматически управляет процессом.

1.  **Генерация Inventory:** Vagrant создает временный inventory-файл, в который добавляет все машины, определенные в `Vagrantfile`, с нужными параметрами SSH-подключения (хост, порт, приватный ключ).
2.  **Ограничение выполнения (`--limit`):** Для **каждой машины отдельно** Vagrant запускает `ansible-playbook` с флагом `--limit <имя_текущей_машины>`. Это гарантирует, что плейбук применяется только к той ВМ, которая в данный момент настраивается.

**Ключевой момент:** Вам **не нужно** вручную указывать `ansible.limit` в `Vagrantfile`, если вы полагаетесь на автоматически сгенерированный inventory. Vagrant делает это за вас.

#### Что если использовать собственный inventory?

Если вы задаёте собственный inventory через `ansible.inventory_path`, Vagrant **не генерирует свой inventory и не добавляет `--limit` автоматически**. В этом случае `ansible.limit` может быть нужен, если вы хотите явно контролировать, на каких хостах запускать плейбук.

## Другие провижинеры

| Провижинер | Пример в `Vagrantfile` | Описание |
| --- | --- | --- |
| `puppet` | `config.vm.provision "puppet", manifest: "default.pp"` | Применяет манифесты Puppet. |
| `docker` | `config.vm.provision "docker", run: "nginx"` | Устанавливает Docker и запускает указанные контейнеры внутри ВМ. |
