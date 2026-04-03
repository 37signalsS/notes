# RBD: Установка и настройка клиента

## Определения и базовые концепции

**ceph-common** — пакет утилит клиента Ceph, включающий `rbd`, `ceph`, `rados`. Версия клиента должна быть совместима с версией сервера.

**Конфигурация клиента:**

| Файл | Назначение |
|------|------------|
| `/etc/ceph/ceph.conf` | Конфигурация кластера (MON-хосты, параметры) |
| `/etc/ceph/ceph.client.<user>.keyring` | Ключ аутентификации клиента |

> **Важно:** Версия `ceph-common` на клиенте должна совпадать или быть младше версии сервера Ceph. Несовместимость версий может привести к ошибкам подключения.

---

## Практические сценарии

### Установка ceph-common

**Debian/Ubuntu (системный репозиторий):**

```bash
sudo apt update
sudo apt install -y ceph-common
```

**CentOS/RHEL:**

```bash
sudo yum install -y ceph-common
```

**Установка из репозитория Ceph (актуальная версия):**

```bash
wget -q -O- 'https://download.ceph.com/keys/release.asc' | sudo apt-key add -
echo "deb https://download.ceph.com/debian-reef/ $(lsb_release -sc) main" | \
  sudo tee /etc/apt/sources.list.d/ceph.list
sudo apt update
sudo apt install -y ceph-common
```

### Настройка конфигурации

**Вариант 1: Копирование с сервера Ceph (рекомендуется)**

```bash
sudo mkdir -p /etc/ceph
sudo scp user@ceph-node:/etc/ceph/ceph.conf /etc/ceph/
```

**Вариант 2: Ручное создание:**

```bash
sudo tee /etc/ceph/ceph.conf <<EOF
[global]
mon_host = 172.21.0.10,172.21.0.11,172.21.0.12
EOF
```

**Копирование ключа аутентификации:**

```bash
sudo scp user@ceph-node:/etc/ceph/ceph.client.user.keyring /etc/ceph/
sudo chmod 600 /etc/ceph/ceph.client.user.keyring
```

### Проверка подключения

```bash
ceph --name client.user -s
```

Команда выводит статус кластера. Успешное выполнение подтверждает корректность конфигурации и аутентификации.

---

## Дополнительная информация

- [Официальная документация Ceph](https://docs.ceph.com/en/latest/rbd/rbd-admin/)
- [Определения и концепции](./definitions_and_concepts.md) — требования к клиенту, image-features
- [Управление образами](./image_management.md) — создание, изменение, удаление
- [Маппинг и монтирование](./mapping_and_mounting.md) — работа с устройствами
