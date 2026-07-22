# RBD: Установка и настройка клиента

## Определения

**ceph-common** — основной пакет утилит клиента Ceph. Включает инструменты `rbd` (управление образами), `ceph` (мониторинг кластера) и `rados` (низкоуровневые операции с объектами).

**Keyring (Ключ доступа)** — файл, содержащий имя пользователя и секретный ключ для аутентификации в кластере Ceph через протокол cephx.

**ceph.conf** — основной конфигурационный файл клиента, содержащий адреса мониторов (MON) и глобальные параметры безопасности.

## Основные концепции

### Совместимость версий
Версия пакета `ceph-common` на клиентских машинах должна быть **не ниже** версии мониторов в кластере Ceph для обеспечения поддержки всех доступных функций. Клиент версии Squid (19.x) обратно совместим с серверами Reef (18.x) и Quincy (17.x).

### Требования к ОС
Для работы RBD клиент должен поддерживать:
- **Модуль ядра rbd**: Должен быть загружен (`modprobe rbd`) или вкомпилирован в ядро.
- **Сетевой доступ**: Открытые порты TCP (по умолчанию 6789 для MON и 6800-7300 для OSD) до узлов кластера.

---

## Практические сценарии

### Установка ceph-common

Рекомендуется использовать официальные репозитории Ceph для получения актуальной версии (Squid).

#### Ubuntu 24.04 / Debian 12

```bash
# Установка зависимостей
sudo apt update && sudo apt install -y curl gnupg2

# Добавление GPG ключа (современный метод без apt-key)
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.ceph.com/keys/release.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/ceph.gpg

# Добавление репозитория Squid
# Замените 'noble' на 'bookworm' для Debian 12
echo "deb [signed-by=/etc/apt/keyrings/ceph.gpg] https://download.ceph.com/debian-squid/ noble main" | \
  sudo tee /etc/apt/sources.list.d/ceph.list

sudo apt update
sudo apt install -y ceph-common
# → ceph version 19.2.0 (squid)
```

#### RHEL / CentOS / Rocky Linux (DNF)

```bash
# Установка репозитория EPEL и Ceph Release
sudo dnf install -y epel-release
sudo dnf install -y https://download.ceph.com/rpm-squid/el9/noarch/ceph-release-1-1.el9.noarch.rpm

# Установка клиента
sudo dnf install -y ceph-common
```

### Настройка конфигурации

Для работы клиента необходимо создать директорию `/etc/ceph` и разместить в ней конфигурационный файл и ключ.

**1. Подготовка конфигурации:**
Если кластер развернут через `cephadm`, минимальный конфиг можно получить с любого узла кластера:
```bash
sudo mkdir -p /etc/ceph
sudo scp user@ceph-node:/etc/ceph/ceph.conf /etc/ceph/
```

**2. Настройка ключа доступа:**
Ключ должен иметь строго ограниченные права доступа.
```bash
sudo scp user@ceph-node:/etc/ceph/ceph.client.admin.keyring /etc/ceph/
sudo chmod 600 /etc/ceph/ceph.client.admin.keyring
```

### Проверка установки и подключения

**1. Проверка модуля ядра:**
```bash
sudo modprobe rbd
lsmod | grep rbd
# → rbd                   114688  0
```

**2. Проверка статуса кластера:**
```bash
ceph -s
# → cluster: ... health: HEALTH_OK ...
```

**3. Проверка версии утилиты:**
```bash
rbd --version
# → ceph version 19.2.0 (squid)
```

---

## Дополнительная информация

- [Официальная документация Ceph (Installation)](https://docs.ceph.com/en/latest/install/)
- [Определения и концепции RBD](./definitions_and_concepts.md)
- [Маппинг и монтирование образов](./mapping_and_mounting.md)
