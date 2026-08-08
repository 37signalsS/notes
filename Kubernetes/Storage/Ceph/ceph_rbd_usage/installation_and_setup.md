# RBD: Установка и настройка клиента

Документ является основным руководством (SSoT) по подготовке клиентской среды для работы с блочными устройствами Ceph (RBD).

## Определения

**ceph-common** — базовый пакет утилит, необходимый для взаимодействия с кластером Ceph. Включает инструменты командной строки:
*   `rbd` — управление образами, снапшотами и клонами.
*   `ceph` — мониторинг состояния кластера и изменение конфигурации.
*   `rados` — низкоуровневые операции с объектами RADOS.

**Keyring (Связка ключей)** — файл, содержащий имя пользователя Ceph и его секретный ключ. Используется для аутентификации в кластере через протокол **CephX**.

**ceph.conf** — файл конфигурации, определяющий параметры подключения: адреса мониторов (MON), настройки безопасности и специфичные параметры производительности для клиента.

**Messenger v2 (msgr2)** — актуальный протокол сетевого взаимодействия Ceph (использует порты 3300 и 6789), поддерживающий шифрование и сжатие трафика "на лету".

---

## Базовые концепции

### Совместимость версий
Рекомендуется использовать версию `ceph-common`, соответствующую мажорному релизу кластера (например, Squid 19.x). Допускается использование клиента на одну версию ниже (N-1) или выше (N+1), однако для поддержки новых функций (например, шифрования RBD или Snapshot-based Mirroring) версия клиента должна быть актуальной.

### Сетевая связность и Messenger v2
Клиент должен иметь доступ к узлам кластера по следующим портам:
*   **3300/TCP**: Messenger v2 (основной порт для современных инсталляций).
*   **6789/TCP**: Messenger v1 (Legacy/Fallback).
*   **6800–7300/TCP**: Порты OSD-демонов для передачи данных.

### Аутентификация и безопасность (CephX)
Доступ к кластеру осуществляется только при наличии валидного ключа. 
*   **Принцип минимальных привилегий:** Клиенту RBD (например, узлу Kubernetes) не следует выдавать ключ `client.admin`. Необходимо создавать специализированных пользователей с доступом только к нужным пулам (caps: `mon 'allow r' osd 'allow rw pool=kube'`).
*   **Права на файлы:** Конфигурационные файлы и ключи в `/etc/ceph/` должны иметь владельца `root` или `ceph` и права доступа `0600` (для ключей) и `0644` (для конфигов).

### Модуль ядра и krbd
При маппинге образов через ядро (`krbd`) важно соответствие функций образа (`image-features`) возможностям ядра Linux. 
*   **Object-map, fast-diff, deep-flatten**: Требуют ядра версии 5.4+.
*   **Encryption (шифрование)**: Требует ядра 6.1+.
При несоответствии клиент не сможет выполнить `rbd map`.

---

## Практические сценарии

### Установка ceph-common

Для продуктивных сред следует использовать официальные репозитории проекта Ceph.

#### Ubuntu 24.04 (Noble) / Debian 12 (Bookworm)
```bash
# Установка зависимостей
sudo apt update && sudo apt install -y curl gnupg2

# Добавление GPG ключа (Modern APT)
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.ceph.com/keys/release.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/ceph.gpg

# Добавление репозитория (Squid - v19)
echo "deb [signed-by=/etc/apt/keyrings/ceph.gpg] https://download.ceph.com/debian-squid/ $(lsb_release -sc) main" | \
  sudo tee /etc/apt/sources.list.d/ceph.list

sudo apt update
sudo apt install -y ceph-common
```

#### RHEL 9 / Rocky Linux 9
```bash
# Установка EPEL
sudo dnf install -y epel-release

# Добавление репозитория Ceph
sudo dnf install -y https://download.ceph.com/rpm-squid/el9/noarch/ceph-release-1-1.el9.noarch.rpm

# Установка пакетов
sudo dnf install -y ceph-common
```

### Настройка конфигурации и доступа

**1. Генерация минимального конфига (через cephadm):**
Если у вас есть доступ к узлу управления кластером, можно сгенерировать компактный файл:
```bash
# Выполнить на узле управления
ceph config generate-minimal-conf > ceph.conf
```

**2. Ручное развертывание на клиенте:**
```bash
sudo mkdir -p -m 755 /etc/ceph

# Копирование конфига и ключа (безопасный метод)
sudo scp user@ceph-mon:/etc/ceph/ceph.conf /etc/ceph/
sudo scp user@ceph-mon:/etc/ceph/ceph.client.user.keyring /etc/ceph/

# Установка корректных прав
sudo chown root:root /etc/ceph/ceph.conf /etc/ceph/ceph.client.user.keyring
sudo chmod 644 /etc/ceph/ceph.conf
sudo chmod 600 /etc/ceph/ceph.client.user.keyring
```

### Проверка и диагностика подключения

**1. Проверка загрузки модуля ядра:**
```bash
sudo modprobe rbd
lsmod | grep rbd
# → rbd                   114688  0
```

**2. Тестирование связи с кластером:**
Команда должна вернуть краткий статус без ошибок аутентификации.
```bash
ceph -s
# → cluster: [fsid] health: HEALTH_OK ...
```

**3. Просмотр возможностей клиента:**
```bash
rbd --version
# → ceph version 19.2.0 (squid)
```

---

## Дополнительная информация

### Связанные темы
- [Определения и базовые концепции RBD](./definitions_and_concepts.md) — архитектурные основы.
- [Маппинг и монтирование образов](./mapping_and_mounting.md) — использование RBD в ОС.
- [Продвинутая настройка и оптимизация](./advanced_topics.md) — кэширование, QoS и шифрование.

### Ссылки
- [Ceph Installation Guide](https://docs.ceph.com/en/latest/install/) — официальная документация по установке.
- [Messenger v2 Specification](https://docs.ceph.com/en/latest/rados/configuration/msgr2/) — детали сетевого протокола.
- [CephX Authentication](https://docs.ceph.com/en/latest/rados/operations/authentication/) — подробности безопасности.
