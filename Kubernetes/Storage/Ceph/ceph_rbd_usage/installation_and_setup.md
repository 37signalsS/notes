# RBD: Установка и настройка клиента

Документ является основным руководством (SSoT) по подготовке клиентской среды для работы с блочными устройствами Ceph (RBD). Описывает установку пакетов, настройку конфигурации, управление ключами CephX, проверку сетевой связности и диагностику подключения к кластеру.

## Определения

**ceph-common** — базовый пакет утилит, необходимый для взаимодействия с кластером Ceph. Включает инструменты командной строки:
*   `rbd` — управление образами, снапшотами и клонами.
*   `ceph` — мониторинг состояния кластера и изменение конфигурации.
*   `rados` — низкоуровневые операции с объектами RADOS.
*   `crushmap` — утилита управления CRUSH-картой (топология кластера).

**CephX** — протокол аутентификации Ceph, основанный на симметричных ключах (аналог Kerberos). Каждый клиент и сервер имеют пару ключей. Клиент доказывает знание ключа монитору (MON), который выдает ticket. Без валидного ключа доступ к кластеру полностью запрещен.

**Keyring (Связка ключей)** — файл, содержащий имя пользователя Ceph и его секретный ключ (а также опциональные caps — ограничения прав). Формат: `[client.username]` + `key = AQ...` + `caps mon = "..." osd = "..."`. Используется для аутентификации через CephX.

**ceph.conf** — файл конфигурации, определяющий параметры подключения: адреса мониторов (MON), настройки безопасности и специфичные параметры производительности для клиента. Минимальный конфиг содержит секцию `[global]` с `mon_host` и `auth_service_required`.

**cephadm** — официальный оркестратор Ceph для развёртывания и управления кластером. Использует контейнеры (Docker/Podman) и systemd. Генерирует минимальные конфиги для клиентов через `ceph config generate-minimal-conf`.

**Messenger v2 (msgr2)** — актуальный протокол сетевого взаимодействия Ceph (использует порты 3300 и 6789), поддерживающий шифрование и сжатие трафика "на лету". Рекомендуется для всех новых инсталляций.

**librbd** — пользовательская библиотека Ceph для работы с RBD-образами. Используется QEMU/KVM, Ceph CSI и другими клиентами в пространстве пользователя. В отличие от krbd, поддерживает кэширование, PWL, шифрование и QoS (см. [Продвинутая оптимизация](./advanced_topics.md#выбор-клиента-krbd--vs-librbd-vs-rbd-nbd)).

---

## Базовые концепции

### Совместимость версий клиента и кластера

Рекомендуется использовать версию `ceph-common`, соответствующую мажорному релизу кластера. Допускается отклонение на одну версию (N-1 или N+1), однако для поддержки новых функций версия клиента должна быть актуальной.

| Релиз Ceph | Кодовое имя | Год | Минимальный клиент | Максимальный клиент |
| :--- | :--- | :--- | :--- | :--- |
| 18.x | Reef | 2023 | 17.x (Quincy) | 19.x (Squid) |
| 19.x | Squid | 2024 | 18.x (Reef) | 20.x (Tentacle) |
| 20.x | Tentacle | 2025 | 19.x (Squid) | 21.x (Umbrella) |
| 21.x | Umbrella | 2026 | 20.x (Tentacle) | — |

**Важно:** При несоответствии версий возможны ошибки протокола. Всегда проверяйте `ceph --version` на клиенте и `ceph -s` на кластере.

### Модуль ядра и krbd
При маппинге образов через ядро (`krbd`) важно соответствие функций образа (`image-features`) возможностям ядра Linux:

| Функция | Минимальное ядро | Описание |
| :--- | :--- | :--- |
| `layering` | 2.6.32 | Клонирование и снапшоты (CoW/RoW) |
| `exclusive-lock` | 3.14 | Эксклюзивная блокировка |
| `object-map` | 3.14 | Ускорение работы с большими образами |
| `fast-diff` | 3.14 | Быстрое определение измененных блоков |
| `deep-flatten` | 5.11 | Deep-flatten |
| `journaling` | 5.14 | Журналирование |
| `encryption` (LUKS) | 6.1 | Клиентское шифрование |

*   **Рекомендация:** Для максимальной совместимости — ядро 5.14+. Для шифрования — ядро 6.1+.
*   При несоответствии клиент не сможет выполнить `rbd map`.

### Сетевая связность и Messenger v2

Клиент должен иметь доступ к узлам кластера по следующим портам:
*   **3300/TCP**: Messenger v2 (основной порт для современных инсталляций).
*   **6789/TCP**: Messenger v1 (Legacy/Fallback).
*   **6800–7300/TCP**: Порты OSD-демонов для передачи данных.

**Требования к сети:**

| Параметр | Требование | Причина |
| :--- | :--- | :--- |
| MTU | Одинаковый на всех интерфейсах (обычно 1500 или 9000) | Jumbo frames предотвращают фрагментацию |
| Firewall | Открыты порты 3300, 6789, 6800-7300 | Блокировка = таймауты маппинга |
| DNS | Резолвинг имён MON | Если `mon_host` указан по имени |
| Latency | < 1ms для локального DC | Высокая латентность = деградация I/O |
| Сетевой интерфейс | Отдельный интерфейс для Ceph (рекомендуется) | Изоляция трафика данных от публичной сети |

**Проверка доступности портов:**
```bash
# Проверка доступности MON
nc -zv ceph-mon-ip 3300
nc -zv ceph-mon-ip 6789

# Проверка OSD-портов (пример для одного OSD)
nc -zv ceph-osd-ip 6800

# Проверка MTU на интерфейсе
ip link show eth0 | grep mtu
# → mtu 9000  (jumbo frames)
```

### Аутентификация и безопасность (CephX)

Доступ к кластеру осуществляется только при наличии валидного ключа.

**Принцип минимальных привилегий:**
Клиенту RBD (например, узлу Kubernetes) не следует выдавать ключ `client.admin`. Необходимо создавать специализированных пользователей с доступом только к нужным пулам:

```bash
# На мониторе: создание пользователя с минимальными правами
ceph auth get-or-create client.rbd-user \
  mon 'allow r' \
  osd 'allow rw pool=kube, allow rw pool=ssd-pool' \
  mgr 'allow r'
# → [client.rbd-user]
#    key = AQAbcDeFgHiJkLmNoPqRsTuVwXyZ1234567890=
#    caps mon = "allow r"
#    caps osd = "allow rw pool=kube, allow rw pool=ssd-pool"
#    caps mgr = "allow r"
```

**Разрешения (caps) — шпаргалка:**

| Caps | Значение | Пример |
| :--- | :--- | :--- |
| `mon` | `allow r` | Чтение состояния кластера |
| `mon` | `allow rw` | Управление конфигурацией |
| `osd` | `allow rw pool=<name>` | Чтение/запись в конкретный пул |
| `osd` | `allow r pool=<name>` | Только чтение из пула |
| `mgr` | `allow r` | Доступ к модулям менеджера |
| `mds` | `allow rw` | Для CephFS (не для RBD) |

**Права на файлы:**
Конфигурационные файлы и ключи в `/etc/ceph/` должны иметь владельца `root` или `ceph` и права доступа `0600` (для ключей) и `0644` (для конфигов):
```bash
sudo chown root:root /etc/ceph/ceph.conf /etc/ceph/ceph.client.*.keyring
sudo chmod 644 /etc/ceph/ceph.conf
sudo chmod 600 /etc/ceph/ceph.client.*.keyring
```

### Отказоустойчивость (High Availability)

Кластер Ceph должен иметь минимум **3 монитора (MON)** для обеспечения кворума. Клиентские конфиги должны содержать адреса ВСЕХ мониторов:

```ini
# Минимальный ceph.conf
[global]
mon_host = 10.0.0.1,10.0.0.2,10.0.0.3
auth_service_required = cephx
auth_client_required = cephx
```

---

## Практические сценарии

### Установка ceph-common

Для продуктивных сред следует использовать официальные репозитории проекта Ceph.

#### Ubuntu 24.04 (Noble) / Debian 12 (Bookworm)
```bash
# Установка зависимостей
sudo apt update && sudo apt install -y curl gnupg2 apt-transport-https

# Добавление GPG ключа (Modern APT)
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.ceph.com/keys/release.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/ceph.gpg

# Добавление репозитория (Squid - v19)
echo "deb [signed-by=/etc/apt/keyrings/ceph.gpg] https://download.ceph.com/debian-squid/ $(lsb_release -sc) main" | \
  sudo tee /etc/apt/sources.list.d/ceph.list

sudo apt update
sudo apt install -y ceph-common
```

#### RHEL 9 / Rocky Linux 9 / AlmaLinux 9
```bash
# Установка EPEL
sudo dnf install -y epel-release

# Добавление репозитория Ceph
sudo dnf install -y https://download.ceph.com/rpm-squid/el9/noarch/ceph-release-1-1.el9.noarch.rpm

# Установка пакетов
sudo dnf install -y ceph-common
```

#### SUSE Leap 15.x / openSUSE Tumbleweed
```bash
# Добавление репозитория Ceph
sudo zypper addrepo https://download.ceph.com/rpm-squid/suse-15.6/ ceph

# Импорт GPG-ключа
sudo rpm --import https://download.ceph.com/keys/release.asc

# Установка пакетов
sudo zypper install -y ceph-common
```

### Настройка конфигурации

#### Вариант 1: Генерация минимального конфига через cephadm
Если у вас есть доступ к узлу управления кластером, можно сгенерировать компактный файл:
```bash
# Выполнить на узле управления кластером
ceph config generate-minimal-conf > ceph.conf

# Просмотр результата
cat ceph.conf
# → [global]
# → mon_host = 10.0.0.1,10.0.0.2,10.0.0.3
# → auth_service_required = cephx
# → auth_client_required = cephx
```

#### Вариант 2: Ручное создание минимального конфига
Если `cephadm` недоступен, создайте конфиг вручную:
```bash
sudo mkdir -p -m 755 /etc/ceph

# Создание минимального ceph.conf
cat <<EOF | sudo tee /etc/ceph/ceph.conf
[global]
mon_host = 10.0.0.1,10.0.0.2,10.0.0.3
auth_service_required = cephx
auth_client_required = cephx

[client]
# Опционально: строка подключения для клиента
# keyring = /etc/ceph/ceph.client.rbd-user.keyring
EOF

sudo chmod 644 /etc/ceph/ceph.conf
```

#### Вариант 3: Копирование конфига с монитора
```bash
# Копирование конфига и ключа (безопасный метод)
sudo scp user@ceph-mon:/etc/ceph/ceph.conf /etc/ceph/
sudo scp user@ceph-mon:/etc/ceph/ceph.client.user.keyring /etc/ceph/

# Установка корректных прав
sudo chown root:root /etc/ceph/ceph.conf /etc/ceph/ceph.client.user.keyring
sudo chmod 644 /etc/ceph/ceph.conf
sudo chmod 600 /etc/ceph/ceph.client.user.keyring
```

### Управление ключами (keyring)

#### Просмотр существующего ключа
```bash
# Просмотр ключа и caps
ceph auth get client.rbd-user
# → [client.rbd-user]
#    key = AQAbcDeFgHiJkLmNoPqRsTuVwXyZ1234567890=
#    caps mon = "allow r"
#    caps osd = "allow rw pool=kube"

# Просмотр только ключа (для вставки в файл)
ceph auth get client.rbd-user --format json | jq -r '.[0].key'
# → AQAbcDeFgHiJkLmNoPqRsTuVwXyZ1234567890=
```

#### Экспорт ключа в файл
```bash
# Экспорт в формате keyring
ceph auth get-or-create client.rbd-user \
  mon 'allow r' \
  osd 'allow rw pool=kube' \
  > /tmp/ceph.client.rbd-user.keyring

# Копирование на клиент
sudo scp /tmp/ceph.client.rbd-user.keyring user@client-node:/etc/ceph/
```

#### Обновление caps (без смены ключа)
```bash
# Изменение разрешений пользователя
ceph auth caps client.rbd-user \
  mon 'allow r' \
  osd 'allow rw pool=kube, allow rw pool=ssd-pool'

# Проверка
ceph auth get client.rbd-user
```

#### Удаление пользователя
```bash
# Внимание: это отзовет ключ у ВСЕХ клиентов, использующих его!
ceph auth del client.rbd-user
```

### Проверка и диагностика подключения

#### 1. Проверка загрузки модуля ядра
```bash
sudo modprobe rbd
lsmod | grep rbd
# → rbd                   114688  0

# Автозагрузка при перезагрузке
echo "rbd" | sudo tee /etc/modules-load.d/rbd.conf
```

#### 2. Проверка версии и функций
```bash
# Версия клиента
rbd --version
# → ceph version 19.2.0 (squid) ...

# Проверка доступных команд
rbd help
```

#### 3. Тестирование связи с кластером
```bash
# Базовая проверка статуса
ceph -s
# → cluster: [fsid]
# →   health: HEALTH_OK
# →   mon: 3 mons at {a=10.0.0.1:6789/0,b=10.0.0.2:6789/0,c=10.0.0.3:6789/0}

# Детальная проверка мониторов
ceph mon dump
# → [0] mon.a 10.0.0.1:6789/0 mon_data_dir=/var/lib/ceph/mon/ceph-a ...
# → [1] mon.b 10.0.0.2:6789/0 ...
# → [2] mon.c 10.0.0.3:6789/0 ...

# Проверка OSD
ceph osd stat
# → 5 osds: 5 up (since ...), 5 in (since ...)

# Проверка пулов
ceph osd pool ls
# → kube
# → ssd-pool
```

#### 4. Проверка аутентификации
```bash
# Тестирование конкретного пользователя
ceph -n client.rbd-user --keyring /etc/ceph/ceph.client.rbd-user.keyring -s
# → cluster: [fsid] ...

# Проверка caps пользователя
ceph auth get client.rbd-user
```

#### 5. Проверка сетевой доступности
```bash
# Проверка портов через nc
for mon in 10.0.0.1 10.0.0.2 10.0.0.3; do
  echo -n "$mon:3300 → "
  nc -zv -w2 $mon 3300 2>&1 | grep -o "succeeded\|timed out\|refused"
done
# → 10.0.0.1:3300 → succeeded
# → 10.0.0.2:3300 → succeeded
# → 10.0.0.3:3300 → succeeded
```

#### 6. Комплексная проверка готовности клиента
```bash
#!/bin/bash
# Quick Ceph client health check
echo "=== Kernel module ==="
lsmod | grep rbd || echo "WARN: rbd module not loaded"

echo -e "\n=== ceph-common version ==="
rbd --version 2>/dev/null || echo "ERROR: ceph-common not installed"

echo -e "\n=== ceph.conf ==="
test -f /etc/ceph/ceph.conf && echo "OK" || echo "ERROR: ceph.conf not found"

echo -e "\n=== Keyring files ==="
ls /etc/ceph/ceph.client.*.keyring 2>/dev/null || echo "WARN: no keyrings found"
ls -la /etc/ceph/ceph.client.*.keyring 2>/dev/null | awk '{print $1, $NF}'

echo -e "\n=== Cluster connectivity ==="
timeout 5 ceph -s 2>/dev/null | head -5 || echo "ERROR: cannot connect to cluster"
```

---

## Дополнительная информация

### Связанные темы
- [Определения и базовые концепции RBD](./definitions_and_concepts.md) — архитектурные основы.
- [Управление образами RBD](./image_management.md) — создание, ресайз, снапшоты, удаление.
- [Маппинг и монтирование образов](./mapping_and_mounting.md) — использование RBD в ОС.
- [Продвинутая настройка и оптимизация](./advanced_topics.md) — кэширование, QoS и шифрование.

### Ссылки
- [Ceph Installation Guide](https://docs.ceph.com/en/latest/install/) — официальная документация по установке.
- [Messenger v2 Specification](https://docs.ceph.com/en/latest/rados/configuration/msgr2/) — детали сетевого протокола.
- [CephX Authentication](https://docs.ceph.com/en/latest/rados/operations/authentication/) — подробности безопасности.
- [Ceph Configuration Reference](https://docs.ceph.com/en/latest/rados/configuration/) — полный справочник параметров конфигурации.
