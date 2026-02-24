# Установка Vagrant

## Определения

**Vagrant** — это программный инструмент, который устанавливается на хост-машину (ваш компьютер или сервер) и позволяет создавать и настраивать легковесные, воспроизводимые и портативные среды разработки.

## Базовые концепции

### Компоненты установки

1. **Основной пакет Vagrant**: Содержит исполняемый файл `vagrant` и базовую логику для управления виртуальными машинами. Рекомендуется устанавливать из официального репозитория HashiCorp для получения актуальной версии.
2. **Плагины (Plugins)**: Дополнительные модули, расширяющие функциональность Vagrant. Самый частый пример — плагины для поддержки различных **провайдеров** (например, `libvirt` или `vmware_desktop`), которые не входят в стандартную поставку.

## Практические сценарии

### Сценарий 1: Установка Vagrant в Debian/Ubuntu

Стандартный процесс включает добавление официального репозитория HashiCorp.

**Шаг 1: Установка зависимостей**

```bash
sudo apt-get update
sudo apt-get install -y curl gpg apt-transport-https
```

**Шаг 2: Добавление GPG-ключа и репозитория HashiCorp**

```bash
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

# Добавить репозиторий
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
```

**Шаг 3: Установка пакета Vagrant**

```bash
sudo apt-get update
sudo apt-get install -y vagrant
```

### Сценарий 2: Установка плагинов

Плагины устанавливаются с помощью встроенной команды `vagrant plugin`.

**Пример: установка провайдера `libvirt` (KVM/QEMU)**

```bash
# Установка плагина vagrant-libvirt
vagrant plugin install vagrant-libvirt
```
