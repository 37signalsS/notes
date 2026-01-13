# Установка Vagrant

## Debian/Ubuntu

Стандартный процесс установки включает добавление официального репозитория HashiCorp для получения последней версии.

```bash
# Обновление списка пакетов и установка зависимостей
sudo apt-get update
sudo apt-get install -y curl gpg apt-transport-https
```

### 1. Добавьте GPG-ключ HashiCorp
Этот ключ необходим для проверки подлинности пакетов.
```bash
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
```

### 2. Добавьте репозиторий HashiCorp
```bash
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
```

### 3. Установите Vagrant
```bash
sudo apt-get update
sudo apt-get install -y vagrant
```

## Установка плагинов

Для расширения функциональности Vagrant использует плагины. Например, для работы с провайдером `libvirt` (KVM/QEMU) необходим соответствующий плагин.

```bash
# Установка плагина vagrant-libvirt
vagrant plugin install vagrant-libvirt
```
