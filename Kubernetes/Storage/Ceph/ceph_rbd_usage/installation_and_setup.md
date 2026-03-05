# RBD: Установка и настройка клиента

## 1. Установка ceph-common

### Debian/Ubuntu

```bash
sudo apt update
sudo apt install -y ceph-common
```

### CentOS/RHEL

```bash
sudo yum install -y ceph-common
```

### Установка из репозитория Ceph

```bash
wget -q -O- 'https://download.ceph.com/keys/release.asc' | sudo apt-key add -
echo "deb https://download.ceph.com/debian-reef/ $(lsb_release -sc) main" | \
  sudo tee /etc/apt/sources.list.d/ceph.list
sudo apt update
sudo apt install -y ceph-common
```

> **Важно**: Используйте версию ceph-common, совместимую с версией сервера Ceph.

---

## 2. Настройка конфигурации

### Копирование конфига с сервера Ceph

```bash
sudo mkdir -p /etc/ceph
sudo scp user@ceph-node:/etc/ceph/ceph.conf /etc/ceph/
```

### Создание конфигурации вручную

```bash
sudo tee /etc/ceph/ceph.conf <<EOF
[global]
mon_host = 172.21.0.10,172.21.0.11,172.21.0.12
EOF
```

### Копирование ключа

```bash
sudo scp user@ceph-node:/etc/ceph/ceph.client.user.keyring /etc/ceph/
sudo chmod 600 /etc/ceph/ceph.client.user.keyring
```

---

## 3. Проверка подключения

```bash
ceph --name client.user -s
```

---

## Ссылки

- **[Управление образами](./image_management.md)** — создание, изменение, удаление
- **[Маппинг и монтирование](./mapping_and_mounting.md)** — работа с устройствами
- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
